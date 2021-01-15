# Ingest AWS Security Hub Events to Azure Sentinel
Author: Sreedhar Ande  

Security Hub is region-specific, which means you need to turn it on and configure it separately for every region in your account.
Ingest all the SecurityHub findings (20 by default) returned by SecurityHub API, ingests only fresh findings based on the LastObservedAt timestamp

## Deploy AWS SecurityHub Data connector
 <a href="https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fandedevsecops%2FAWS-Security-Hub-Data-Connector%2Fmain%2Fazuredeploy_dotcomtenants.json" target="_blank">
    <img src="https://aka.ms/deploytoazurebutton"/>
    </a>
<a href="https://portal.azure.us/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fandedevsecops%2FAWS-Security-Hub-Data-Connector%2Fmain%2Fazuredeploy_dotustenants.json" target="_blank">
<img src="https://raw.githubusercontent.com/Azure/azure-quickstart-templates/master/1-CONTRIBUTION-GUIDE/images/deploytoazuregov.png"/>
</a>

1. Click  "Deploy To Azure"/ "Deploy to Azure Gov"

2. Select the preferred **Subscription**, **Resource Group** and **Location**  
   **Note**  
   Best practice : Create new Resource Group while deploying - all the resources of your custom Data connector will reside in the newly created Resource 
   Group
3. Enter the following value in the ARM template deployment
	```	
	"Workspace Id": Azure Log Analytics Workspace Id​
	"Workspace Key": Azure Log Analytics Workspace Key
	"AWS Access Key Id": AWS Access Key
	"AWS Secret Key ID": AWS Secret Key
	"AWS Region Name" : AWS SecurityHub Region
	"CustomLogTableName": Azure Log Analytics Custom Log Table Name
	"Function Schedule": The `TimerTrigger` makes it incredibly easy to have your functions executed on a schedule. The default **Time Interval** is set to pull
	the last ten (10) minutes of data.
	```

## Post Deployment Steps

1. The `TimerTrigger` makes it incredibly easy to have your functions executed on a schedule. This sample demonstrates a simple use case of calling your function based on your schedule provided while deploying. If the time interval needs to be modified, it is recommended to change the Function App Timer Trigger accordingly update environment variable **"Schedule**" (post deployment) to prevent overlapping data ingestion.
   ```
   a.	Go to your Resource Group --> Click on Function App `awssecurityhub<<uniqueid>>`
   b.	Click on Function App "Configuration" under Settings 
   c.	Click on "Schedule" under "Application Settings"
   d.	Update your own schedule using cron expression.
   ```
   **Note: For a `TimerTrigger` to work, you provide a schedule in the form of a [cron expression](https://en.wikipedia.org/wiki/Cron#CRON_expression)(See the link for full details). A cron expression is a string with 6 separate expressions which represent a given schedule via patterns. The pattern we use to represent every 10 minutes is `0 */10 * * * *`. This, in plain text, means: "When seconds is equal to 0, minutes is divisible by 10, for any hour, day of the month, month, day of the week, or year".**
   
2. AWSAccessKey, AWSSecretAccessKey and Workspace Key will be placed as "Secrets" in the Azure KeyVault `awssecurityhub<<uniqueid>>` with only Azure Function access policy. If you want to see/update these secrets,

	```
		a. Go to Azure KeyVault "awssecurityhub<<uniqueid>>"
		b. Click on "Access Policies" under Settings
		c. Click on "Add Access Policy"
			i. Configure from template : Secret Management
			ii. Key Permissions : GET, LIST, SET
			iii. Select Prinicpal : <<Your Account>>
			iv. Add
		d. Click "Save"

	```
