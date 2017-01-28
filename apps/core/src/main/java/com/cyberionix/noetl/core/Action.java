package com.cyberionix.noetl.core;

import java.util.HashMap;
import java.util.List;
import java.util.ArrayList;
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

    private List<Action> nextActions;
    private List<Action> failActions; // list of actions to be executed in case of current action failure
    private List<Dependency> dependencies; //dependency list that defines execution for current action


    /* processing part */
    private Integer exitCode = null;
    private ActionState state = ActionState.ONHOLD;
    private ActionOutput outputResult = null;

    private class Dependency {
        private String actionName;
        // type of dependency and so on
    }

    /**
     * wrapper for ActionState
     */
    private class ActionStates { // may be we can merge ActionState and ActionStates at some point
        private ActionState actionState;

        ActionStates () {
            this.actionState = ActionState.INITIALIZED;
        }

        ActionStates (ActionState state) {
            this.actionState = state;
        }
        public void setActionState(ActionState state) {
            this.actionState = state;
        }
    }


    /**/
    /**
     * Default constructor initializing ActionList variable.
     *
     */
    Action () {
        if (this.nextActions == null) {
            this.nextActions = new ArrayList<Action>();
            ActionStates actionState = new ActionStates(ActionState.INITIALIZED);
        }
    }
    /**
     * Constructor populate ActionList to create a list of actions to be executed in case of successfully executed current action.
     * @param actionList
     */
    Action (ArrayList<Action> actionList) {
        if (this.nextActions == null) {
            this.nextActions = new ArrayList<Action>();
            this.nextActions.addAll(actionList);
        } else {
            for (Action action : actionList) {
                this.nextActions.add(action);
            }
        }
        ActionStates actionState = new ActionStates(ActionState.INITIALIZED);
    }

    abstract void addNext(Action action);

    abstract void removeNext(String actionId);

    abstract void addProperty(String key,String value);

    abstract void removeProperty(String key);

    /**
     * addActionList method populates a list of next actions that have to be performed next.
     *
     * @param actionList as ArrayList of list of Action objects
     * @throws
     */
    public void addNextActions (ArrayList<Action> actionList) {
        // this.ActionList.addAll(actionList);
        // probably we need to evaluate Actions one by one to handle excpetions if any
        for (Action action : actionList) {
            this.nextActions.add(action);
        }
    }

    /**
     * addActionList method keep adding one Action at a time to ActionList.
     *
     * @param action as object of Action class
     * @throws
     */
    public void addNextAction (Action action) {
            this.nextActions.add(action);
    }


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
    abstract void onStateChanged(); //is called when previous task is changed






}
