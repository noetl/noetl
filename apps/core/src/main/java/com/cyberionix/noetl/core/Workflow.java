package com.cyberionix.noetl.core;

import java.util.Properties;
import java.util.HashMap;

/**
 * Created by refugee on 1/24/17.
 */
public class Workflow {
private String name;
private String description;
private String start;
private HashMap<String,Action> actions;
private Properties properties;

// to define workflow as a service we need to define some kind of API for each initialized workflow (make it as a main listener for all encapsulated actions)

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
