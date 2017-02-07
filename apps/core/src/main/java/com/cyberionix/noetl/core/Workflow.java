package com.cyberionix.noetl.core;

import java.util.Properties;
import java.util.HashMap;

/**
 * Created by refugee on 1/24/17.
 */
public abstract class Workflow {
private String name;
private String description;
private IAction start;
private HashMap<String, IAction> actions;
private Properties properties;


// to define workflow as a service we need to define some kind of API for each initialized workflow (make it as a main listener for all encapsulated actions)

    Workflow () {
        throw new IllegalArgumentException("The path for config file have to be specified");
    }

    Workflow (String actionID, IAction action) {
        addAction(actionID, action);
    }

    private void validateActions(){
        if (this.actions == null) {
            this.actions = new HashMap<String,IAction>();
        }
    }

    public void addAction(String actionID, IAction action) {
        validateActions();
        actions.put(actionID, action);

    }
    public void removeAction(String actionID) {
        if (actions.containsKey(actionID)) {
            actions.remove(actionID);
        }
    }
    abstract void getActionOutput(String key);

    abstract void addProperty(String key, String value);
    abstract void removeProperty(String key);

    public String getName() {
        return name;
    }
    public void   setName(String name) {
        this.name = name;
    }

    public IAction getStart() {
        return start;
    }
    public void  setStart(IAction action) {
        this.start = action;
    }


    public String getDescription() {
        return description;
    }
    public void setDescription(String description) {
        this.description = description;
    }


    public abstract void Execute();

}
