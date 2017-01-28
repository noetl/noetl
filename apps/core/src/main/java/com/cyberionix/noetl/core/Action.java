package com.cyberionix.noetl.core;

import java.util.HashMap;
import java.util.Properties;

/**
 * Created by refugee on 1/24/17.
 */

public abstract class Action {

    /* declarative part */
    private String actionType; //e.g. CLI,DB,REST...
    private String name;
    private String description;
    private Properties properties;

    private HashMap<String,Action> next;


    /* processing part */
    private Integer exitCode = null;
    private ActionState state = ActionState.Onhold;
    private ActionOutput outputResult = null;


    /**/

    abstract void addNext(Action action);
    abstract void removeNext(String actionId);

    abstract void addProperty(String key,String value);
    abstract void removeProperty(String key);


    public String getName() {
        return name;
    }
    public void   setName(String name) {
        this.name = name;
    }

    public String getDescription() {
        return description;
    }
    public void setDescription(String description) {
        this.description = description;
    }

    abstract void Execute(); //inside shoud be calls to onStateChanged()

    abstract void myStateIsChanged(); //here nexts should be informed
    abstract void onStateChanged(Action action); //??? is called when previous task is changed






}
