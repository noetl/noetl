package com.cyberionix.noetl.core;

import com.typesafe.config.*;
import java.util.Properties;
import java.util.HashMap;
import java.io.File;

/**
 * Created by refugee on 1/24/17.
 */
public class Workflow {
private String name;
private String description;
private String start;
private HashMap<String,Action> actions;
private Properties properties;
private Config config;


// to define workflow as a service we need to define some kind of API for each initialized workflow (make it as a main listener for all encapsulated actions)

    Workflow () {
        throw new IllegalArgumentException("The path for config file have to be specified");
    }

    Workflow (String path) {
        ConfigParseOptions options = ConfigParseOptions.defaults();
        //System.out.printf("Workflow path %s%n",path);
        Config parsedConfig = ConfigFactory.parseFile(new File(path),options); //(new File(path));
        //System.out.printf("parsedConfig %s%n",parsedConfig.toString());
        this.config = ConfigFactory.load(parsedConfig);
        //System.out.printf("this.config %s%n",this.config.toString());
    }

    public static void main(String[] args) {
        if (args[0] == null) {
            throw new IllegalArgumentException("The path for config file have to be specified");
        }

        System.out.printf("args[0] %s%n",args[0]);
        Workflow workflow = new Workflow(args[0]);

        String WorkflowID =  workflow.config.getString("WORKFLOW.ID");

        System.out.printf("Config test %s",WorkflowID);
    }

    public void initiateActions() {
        // we need to build Action chain from here
    }

    public void readConfig() {

        //deserialize workflow
    }

    public void writeConfig(){


        // serialize workflow
    }



}
