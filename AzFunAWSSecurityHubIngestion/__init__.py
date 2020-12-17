import requests
import datetime
import dateutil
import logging
import boto3
import gzip
import io
import csv
import time
import os
import sys
import json
import hashlib
import hmac
import base64
from threading import Thread
from io import StringIO

import azure.functions as func


sentinel_customer_id = os.environ.get('WorkspaceID')
sentinel_shared_key = os.environ.get('WorkspaceKey')
aws_access_key_id = os.environ.get('AWSAccessKeyId')
aws_secret_acces_key = os.environ.get('AWSSecretAccessKey')
aws_region_name = os.environ.get('AWSRegionName')
sentinel_log_type = 'AWS_SecurityHub'


def main(mytimer: func.TimerRequest) -> None:
    if mytimer.past_due:
        logging.info('The timer is past due!')

    logging.info('Starting program')
    
    sentinel = AzureSentinelConnector(sentinel_customer_id, sentinel_shared_key, sentinel_log_type, queue_size=10000, bulks_number=10)
    cli = SecurityHubClient(aws_access_key_id, aws_secret_acces_key, aws_region_name)

    results = cli.getFindings()    
    fresh_events_after_this_time = cli.freshEventTimestampGenerator()
    fresh_events = True
    first_call = True   
    
    while ((first_call or 'NextToken' in results) and fresh_events):
        # Loop through all findings (20 by default) returned by Security Hub API call
		# If finding has the string "SENT TO LAW" in the finding note, the event is not sent but
		# loop will continue.
		# Fresh events will be sent to LAW API, "SENT TO LAW" will
		# be prefixed to the finding's note.
		# Break out of the loop when we have looked back across the last hour of events (based on the
		# finding's LastObservedAt timestamp)
        first_call = False
        
        for finding in results['Findings']:
            finding_timestamp = cli.findingTimestampGenerator(finding['LastObservedAt'])
            already_sent = False
            existing_note = ''
            principal = 'SecurityHubLambda'
            if 'Note' in finding:
                if 'SENT TO LAW:' in finding['Note']['Text']:
                    already_sent = True
                else:
                    existing_note = finding['Note']['Text']
                    principal = finding['Note']['UpdatedBy']
            
            if (finding_timestamp > fresh_events_after_this_time and not already_sent):
                payload = {}
                payload.update({'sourcetype':'aws:securityhub'})
                payload.update({'event':json.dumps(finding)})
                
                filters = {
					'Id': [
				         { 
				            'Comparison': 'EQUALS',
				            'Value': finding['Id']
				         }
				      ],
				    'LastObservedAt': [
				         { 
				            'Start': finding['LastObservedAt'],
				            'End': finding['LastObservedAt']
				         }
				      ],
				}
                
                sentinel.send(payload)
                if not sentinel.failedToSend:
                    print('Event successfully sent to LAW')
                    sentinel.failedToSend = False
                    cli.updateFindingNote(existing_note, principal, filters)
                    failed_sent_events_number += sentinel.failed_sent_events_number
                    successfull_sent_events_number += sentinel.successfull_sent_events_number
                else:
                    print('Event NOT successfully sent to LAW')
            else:
                fresh_events = False
                break
            
            if (fresh_events):
                results = cli.getFindingsWithToken(results['NextToken'])
    
    if failed_sent_events_number:
        logging.error('{} events have not been sent'.format(failed_sent_events_number))

    logging.info('Program finished. {} events have been sent. {} events have not been sent'.format(successfull_sent_events_number, failed_sent_events_number))


class SecurityHubClient:
    def __init__(self, aws_access_key_id, aws_secret_acces_key, aws_region_name):
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_acces_key = aws_secret_acces_key
        self.aws_region_name = aws_region_name        
        self.total_events = 0
        self.input_date_format = '%Y-%m-%d %H:%M:%S'
        self.output_date_format = '%Y-%m-%dT%H:%M:%SZ'

        self.securityhub = boto3.client(
            'securityhub',
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_acces_key,
            region_name=self.aws_region_name
        )    

    def freshEventTimestampGenerator(self):
        tm = datetime.datetime.utcfromtimestamp(time.time())
        return time.mktime((tm - datetime.timedelta(minutes=60)).timetuple())

    # Gets the epoch time of a UTC timestamp in a Security Hub finding
    def findingTimestampGenerator(self, finding_time):
        d = dateutil.parser.parse(finding_time)
        d.astimezone(dateutil.tz.tzutc())
        return time.mktime(d.timetuple())

    # Gets 20 most recent findings from securityhub
    def getFindings(self, filters={}):
        return self.securityhub.get_findings(Filters=filters)

    # Gets 20 most recent findings from securityhub
    def updateFindingNote(self, existing_note, principal, filters={}):
        return self.securityhub.update_findings(
            Filters=filters,
	        Note={
	    	    'Text': 'SENT TO LAW: %s' % existing_note,
	    	    'UpdatedBy': principal
	        }
	    )

    # Gets 20 findings from securityhub using the NextToken from a previous request
    def getFindingsWithToken(self, token, filters={}):
        return self.securityhub.get_findings(
	        Filters=filters,
	        NextToken=token
	    )


class AzureSentinelConnector:
    def __init__(self, customer_id, shared_key, log_type, queue_size=200, bulks_number=10, queue_size_bytes=25 * (2**20)):
        self.customer_id = customer_id
        self.shared_key = shared_key
        self.log_type = log_type
        self.queue_size = queue_size
        self.bulks_number = bulks_number
        self.queue_size_bytes = queue_size_bytes
        self._queue = []
        self._bulks_list = []
        self.successfull_sent_events_number = 0
        self.failed_sent_events_number = 0
        self.failedToSend = False

    def send(self, event):
        self._queue.append(event)
        if len(self._queue) >= self.queue_size:
            self.flush(force=False)

    def flush(self, force=True):
        self._bulks_list.append(self._queue)
        if force:
            self._flush_bulks()
        else:
            if len(self._bulks_list) >= self.bulks_number:
                self._flush_bulks()

        self._queue = []

    def _flush_bulks(self):
        jobs = []
        for queue in self._bulks_list:
            if queue:
                queue_list = self._split_big_request(queue)
                for q in queue_list:
                    jobs.append(Thread(target=self._post_data, args=(self.customer_id, self.shared_key, q, self.log_type, )))

        for job in jobs:
            job.start()

        for job in jobs:
            job.join()

        self._bulks_list = []

    def __enter__(self):
        pass

    def __exit__(self, type, value, traceback):
        self.flush()

    def _build_signature(self, customer_id, shared_key, date, content_length, method, content_type, resource):
        x_headers = 'x-ms-date:' + date
        string_to_hash = method + "\n" + str(content_length) + "\n" + content_type + "\n" + x_headers + "\n" + resource
        bytes_to_hash = bytes(string_to_hash, encoding="utf-8")  
        decoded_key = base64.b64decode(shared_key)
        encoded_hash = base64.b64encode(hmac.new(decoded_key, bytes_to_hash, digestmod=hashlib.sha256).digest()).decode()
        authorization = "SharedKey {}:{}".format(customer_id, encoded_hash)
        return authorization

    def _post_data(self, customer_id, shared_key, body, log_type):
        events_number = len(body)
        body = json.dumps(body)
        method = 'POST'
        content_type = 'application/json'
        resource = '/api/logs'
        rfc1123date = datetime.datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
        content_length = len(body)
        signature = self._build_signature(customer_id, shared_key, rfc1123date, content_length, method, content_type, resource)
        uri = 'https://' + customer_id + '.ods.opinsights.azure.com' + resource + '?api-version=2016-04-01'

        headers = {
            'content-type': content_type,
            'Authorization': signature,
            'Log-Type': log_type,
            'x-ms-date': rfc1123date
        }

        response = requests.post(uri, data=body, headers=headers)
        if (response.status_code >= 200 and response.status_code <= 299):
            logging.info('{} events have been successfully sent to Azure Sentinel'.format(events_number))
            self.successfull_sent_events_number += events_number
            self.failedToSend = False
        else:
            logging.error("Error during sending events to Azure Sentinel. Response code: {}".format(response.status_code))
            self.failed_sent_events_number += events_number
            self.failedToSend = True

    def _check_size(self, queue):
        data_bytes_len = len(json.dumps(queue).encode())
        return data_bytes_len < self.queue_size_bytes

    def _split_big_request(self, queue):
        if self._check_size(queue):
            return [queue]
        else:
            middle = int(len(queue) / 2)
            queues_list = [queue[:middle], queue[middle:]]
            return self._split_big_request(queues_list[0]) + self._split_big_request(queues_list[1])

