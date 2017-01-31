package com.cyberionix.noetl.core;

import com.typesafe.config.Config;
import com.typesafe.config.ConfigFactory;
import com.typesafe.config.ConfigParseOptions;

import java.io.File;

/**
 * Created by Davit on 01.31.2017.
 */
public class WorkflowBuilderJSON {

    private Config config;


    WorkflowBuilderJSON(String path) {
        ConfigParseOptions options = ConfigParseOptions.defaults();
        //System.out.printf("Workflow path %s%n",path);
        Config parsedConfig = ConfigFactory.parseFile(new File(path),options); //(new File(path));
        //System.out.printf("parsedConfig %s%n",parsedConfig.toString());
        this.config = ConfigFactory.load(parsedConfig);
        //System.out.printf("this.config %s%n",this.config.toString());
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

    public static void main(String[] args) {
        if (args[0] == null) {
            throw new IllegalArgumentException("The path for config file have to be specified");
        }

        System.out.printf("args[0] %s%n",args[0]);
        WorkflowBuilderJSON workflow = new WorkflowBuilderJSON(args[0]);

        String WorkflowID =  workflow.config.getString("WORKFLOW.ID");
        System.out.printf("Config test %s",WorkflowID);
    }
}
