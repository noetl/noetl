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

    abstract void addAction(String key,Action action);
    abstract void removeAction(String key);

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
