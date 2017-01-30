package com.cyberionix.noetl.core;

import java.util.Properties;
import java.util.HashMap;

/**
 * Created by refugee on 1/24/17.
 */
public abstract class Workflow {
private String name;
private String description;
private String start;
private HashMap<String,Action> actions;
private Properties properties;

    abstract void addProperty(String key,String value);
    abstract void removeProperty(String key);
// to define workflow as a service we need to define some kind of API for each initialized workflow (make it as a main listener for all encapsulated actions)

    public void initiateActions() {
        // we need to build Action chain from here
    }
    abstract void addAction(String key,Action action);
    abstract void removeAction(String key);

    public void readConfig() {

        //deserialize workflow
    }

    public void writeConfig(){


        // serialize workflow
    }



    public String getName() {
        return name;
    }
    public void   setName(String name) {
        this.name = name;
    }

    public String getStart() {
        return start;
    }
    public void   setStart(String name) {
        this.start = start;
    }


    public String getDescription() {
        return description;
    }
    public void setDescription(String description) {
        this.description = description;
    }


    public abstract void Execute();

}