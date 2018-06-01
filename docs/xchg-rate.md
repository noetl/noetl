# This script should do the following:
1. Request BTC/USD exchange rate from 3 different cryptocurrency exchanges using their public APIs.
The calls to exchanges shall be done in parallel.
2. Receive a response from each exchange and transform it to canonical data model.
3. Calculate average composite exchange rate using exchange rates from different exchanges.
4. Write the exchange rate into the database.

## The script format shall comply with JSON specifications, except for comments:
a. http://www.ecma-international.org/publications/files/ECMA-ST/ECMA-404.pdf

b. https://tools.ietf.org/html/rfc8259

That means two important implications.
1. A valid JSON document is a `value`, but not a `member`, so cannot start with a `name`.
In other words, `{ "displayName": "value" }` is a valid JSON document,
but `"displayName" : { ... }` is NOT.
2. Arrays shall contain only values, but not members:
`[ {...}, 1, true, null, {...} ]` is a valid JSON array,
but `[ "displayName":{...} ]` is NOT.

Canonical representation of the BTC/USD exchange rate is a JSON object:

 `{"BTC/USD":"9328.39","timestamp":"2018-04-30T19:51:12.876Z"}`
 
_Note that the rate value MUST be quoted as string._

/----------------------------------------------------------------------------/

Keywords in workflow configurations are case-sensitive.
Keyword naming convention:
- keywords MUST include only capital and small latin letters [A-Z,a-z], decimal digits [0-9] and underscore [_];
- keywords MUST begin from a capital or small latin letter [A-Z,a-z];
- keywords MUST end only with a capital or small latin letter [A-Z,a-z] or a decimal digit [0-9].

/-----------------------------------------------------------------------------/

Naming convention of member names:
- member names are case-sensitive;
- member names MUST include only capital and small latin letters [A-Z,a-z], decimal digits [0-9] and underscore [_];
- member names MUST begin from a capital or small latin letter [A-Z,a-z];
- member names MUST end only with a capital or small latin letter [A-Z,a-z] or a decimal digit [0-9].

/-----------------------------------------------------------------------------/

Top-level JSON object. This is requred by the JSON specification.
Object can be changed to arrays in the future.
```{
	// Workflow is a container for actions that represents an execution flow.
	// Each config file shall have exactly one workflow object at this moment.
	"workflow1": { // this is a member name of the workflow, it must be unique within the file


		// Object type is a mandatory attributes that must be present in every object.
		"type": "workflow", // Type unambiguously determines the type of each object, here it is a workflow.
		"displayName": "BTC/USD average exchange rate", // Display name is what will be displayed in the graphical user interface.

		// Description is optional, but provides valuable information to users, especially those using GUI
		"description": "Retrieves BTC/USD exchange rate from 3 different exchanges, calculates an average and puts the latter into db",

		// Input object represents key/value pairs that allow for parameterization of the workflow.
		"input": { "httpClientTimeout": "${httpClientTimeout}" },

		// Workflow starts from the start action(s) whose ids are listed in the array.
		// Note: start emits input data of the workflow to each action in the start array.
		"start": ["fork1"], // name(s) of start action(s)

		// Fork represents diverging to multiple flows executed in parallel.
		// Fork copies input data to all of its outputs unchanged (fan-out).
		"fork1": { // "fork1" is an object identifier
			"type": "fork",
			"displayName": "fork1",
			"description": "Starts parallel execution",
			"next": ["websvc101", "websvc201", "websvc301"],
		},
		// Actually, the above fork is not necessary in this workflow,
		// because multiple parallel actions can diverge directly "start",
		// but is depicted for clarity.


		// Web service action calls a HTTP(S) URI to perform an action.
		// HTTP verbs shall be put into "httpMethod" attribute.
		// Parameters can be sent as:
		// a) part of URL for GET requests;
		// b) application/x-www-form-urlencoded for POST/PUT/PATCH/DELETE requests;
		// c) application/json for for POST/PUT/PATCH/DELETE requests.
		// Result format depends on the called service.
		// Parameters are supplied from its input data.
		// Result will be conveyed to all actions listed in next actions array.

		// CEX.io provides BTC/USD price as GET URI with result in JSON
		// Example: GET https://cex.io/api/last_price/BTC/USD
		"websvc101": {
			"type": "webservice",
			"displayName": "CEX.io",
			"description": "Request BTC/USD rate from CEX.io",
			"next": ["websvc102"],
			"run": {
			  "httpClientTimeout": "${inputData.httpClientTimeout}",
			  "httpMethod": "GET",
			  "url": "https://cex.io/api/last_price/BTC/USD",
			  "output": "${responseBody}", // this sends http response body to next actions
			  }
		},

		// Hypothetical web service that transforms CEX.io responses to canonical form.
		"websvc102": {
			"type": "webservice",
			"displayName": "CEX.io-Transform",
			"description": "Transforms answer from CEX.io to a canonical form",
			"next": ["join401"],
			"run": {
			  "httpClientTimeout": "${inputData.httpClientTimeout}",
			  "httpMethod": "POST", // request method
			  "contentType": "application/json", // request Content-Type
			  "url": "https://localservice.noetl.io/transform-cexio",
			  "requestBody": "${input}", // data received from the previous action
			"output": "${responseBody}", // canonical form is also JSON object
			}
		},

		// Bitfinex also provides tickets as GET URI with result as JSON:
		// GET https://api.bitfinex.com/v1/pubticker/btcusd
		"websvc201": {
			"type": "webservice",
			"displayName": "Bitfinex",
			"description": "Request BTC/USD rate from Bitfinex",
			"next": ["jdbc202"],
			"run": {
			  "httpClientTimeout": "${inputData.httpClientTimeout}",
			  "httpMethod": "GET",
			  "url": "https://api.bitfinex.com/v1/pubticker/btcusd",
			  "output": "${responseBody}"
			}
		},

		// JDBC action makes a call to a JDBC database.
		// Here we call a hypothetical PostgreSQL function that converts Bitfinex JSON to a canonical JSON form.
		"jdbc202": {
			"type": "jdbc",
			"displayName": "Bitfinex-Transform",
			"description": "Transforms answer from Bitfinex to a canonical form",
            "next": ["join401"],
			// need to decide how to put passwords into config files
			"run": {
			"databaseURL": "jdbc:postgresql://localhost/test?user=fred&password=secret&ssl=true",
			"queryString": "SELECT public.bitfinex_to_canonical($1)",
			"queryParams": [ "${input}" ], // data received from the previous action
			"output": "${queryResult}", // PostgreSQL can transform JSON!
			}
		},

		// HitBTC also provides BTC/USD ticket as JSON to GET request.
		// GET https://api.hitbtc.com/api/2/public/ticker/BTCUSD
		"websvc301": {
			"type": "webservice",
			"displayName": "HitBTC",
			"description": "Request BTC/USD rate from HitBTC",
            "next": ["shell302"],
			"run": {
			  "httpClientTimeout": "${inputData.httpClientTimeout}",
			  "httpMethod": "GET",
			  "url": "https://api.hitbtc.com/api/2/public/ticker/BTCUSD",
			  "output": "${responseBody}", // this sends http response body to next actions
			}
		},

		// shellTask invokes local shell, which means:
		// a) the engine must execute on Linux/Unix machine;
		// b) commands must be specific only to local host.
		"shell302": {
			"type": "shell",
			"displayName": "HitBTC-Transform",
			"description": "Transforms answer from HitBTC to a canonical form",
            "next": ["join401"],
			"run": {
			  "shellScript": "/usr/local/bin/transform-hitbtc",
			// each element of scriptParams array shall be supplied to shellScript as a parameter beginning from $1 = [0]
			  "scriptParams": [ "${inputData}" ],
			  "output": "${stdout}", // shell's stdout will be copied to next actions
			}
		},


		// Join waits for all incoming flows to execute and combines all inputs from previous actions as an array:
		// "output": [ input1, input2, ... ]
		"join401": {
			"type": "join",
			"displayName": "join401",
			"description": "",
			"next": ["ssh501"]
		},
		// The outputData of this join must be a JSON array of canonical rates:
		// [{"BTC/USD":"9328.39","timestamp":"2018-04-30T19:51:12.876Z"},
		//  {"BTC/USD":"9666.88","timestamp":"2018-04-30T19:51:13.567Z"},
		//  {"BTC/USD":"9481.39","timestamp":"2018-04-30T19:51:13.218Z"}]

		// ssh action is essentially a shell that must be executed on a remote host via SSH.
		// The following ssh action executes a remote script to calculate an average BTC/USD rate.
		"ssh501": {
			"type": "ssh",
			"displayName": "Calc-average",
			"description": "Calculates average BTC/USD rate on a remote host",
            "next": ["scp601"],
			"run": {
			  "sshHost": "scripthost.noetl.io",
			  "sshPort": "22", // note string here, not number!
			  "sshUser": "scripter",
			// Specify a key pair file as SSH identity_file parameter (ssh -i) - see "man ssh".
			// Using password in sshTask is wrong and must be discouraged.
			  "sshIdentityFile": "/home/noetl/ssh-keys/scripthost.pem", // key pair file must reside in local file system
			  "shellScript": "/usr/local/bin/calc-average", // on the remote host
			  "scriptParams": "${input}", // the array of three BTC/USD rates
			}
		},

		// Notice no output from the above ssh action?
		// That is because stupid `/usr/local/bin/calc-average` on the scripthost.noetl.io
		// leaves the result in the file "/usr/local/var/calc-average/current-rate"!
		// No problem, we will get the file from the remote host (though we could just `cat` it from there).

		// scp action securely copies files using SSH protocol.
		"scp601": {
			"type": "scp",
			"displayName": "Transfer average rate",
			"description": "Transfers the average result from remote host to local machine",

			"sourceHost": "scripthost.noetl.io",
			"sourcePort": "22", // note string here, not number!
			"sourceUser": "scripter",
			"sourceIdentifyFile": "/home/noetl/ssh-keys/scripthost.pem", // key pair file must reside in local file system
			"sourcePath": "/usr/local/var/calc-average/current-rate", // that file, yeah!

			"targetHost": "localhost",
			// no targetPort, targetUser, targetIdentityFile are necessary for "localhost"
			"targetPath": "/usr/local/var/calc-average/", // directory name is enough
			"overwriteTarget": "always", // "always", "newer", "never" are sane options

			"next": ["shell701"],
		},
		// No outputData again?!
		// That is because scpTask produces no output data, it is a copy procedure and returns no result.

		// Let's print the file and get the rate!
		"shell701": {
			"type": "shell",
			"displayName": "Print average rate",
			"description": "Prints average BTC/USD rate in the canonical form",
            "next": ["jdbc801"],
			"run": {
			  "shellScript": "cat /usr/local/var/calc-average/current-rate", // local file, remember?
			  "output": "${stdout}" // shell's stdout will be copied to next actions
			}
		},
		// outputshall be a JSON object like following:
		// {"BTC/USD":"9666.88","timestamp":"2018-04-30T19:51:13.567Z"}

		// Finally, let's write the result into the database.
		// Luckily, PostgreSQL accepts and parses JSON as input.
		"jdbc801": {
			"type": "jdbc",
			"displayName": "Save to database",
			"description": "Saves the average BTC/USD rate to database",
            "next": ["end"], // the final destination of each workflow is end
			// need to decide how to put passwords into config files
			"run": {
			  "databaseURL": "jdbc:postgresql://localhost/test?user=fred&password=secret&ssl=true",
			  "queryString": "SELECT public.append_btc_usd_rate($1::json)",
			  "queryParams": [ "${input}" ], // data received from the previous action
			"output": "${queryResult}" // just in case, receive confimation from the database
			}
		},

	} // end of workflow

} // end of JSON document
```