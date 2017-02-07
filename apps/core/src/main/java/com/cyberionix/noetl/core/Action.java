package com.cyberionix.noetl.core;

import java.util.*;

/**
 * Created by refugee on 1/24/17.
 */

public abstract class Action implements IAction{

    /* declarative part */
    private String actionType; //e.g. CLI,DB,REST...
    private String actionID; //must be unique among all action in workflow
    private String name;
    private String description;
    private Properties properties;

    //private HashMap<String,Action> next;
    private List<IAction> nextActions;

    /* processing part */
    private Integer exitCode = null;
    private ActionState state = ActionState.ONHOLD;
    private ActionOutput outputResult = null;

    public String getActionID() {
        return actionID;
    }

    private void setActionID(String actionID) {
        this.actionID = actionID;
    }

    public ActionState getState() {
        return state;
    }

    private void setState(ActionState state) {
        this.state = state;
    }

    public Integer getExitCode() {
        return exitCode;
    }

    public void setExitCode(Integer exitCode) {
        this.exitCode = exitCode;
    }

    public ActionOutput getOutputResult() {
        return outputResult;
    }

    public void setOutputResult(ActionOutput outputResult) {
        this.outputResult = outputResult;
    }

    /**
     * validateNextActions validates this.nextActions and initiates if it's empty.
     */
    private void validateNextActions(){
        if (this.nextActions == null) {
            this.nextActions = new ArrayList<IAction>();
        }
    }

    private Action() {
        throw new AssertionError();
    }

    /**
     * Default constructor initializing ActionList variable.
     * @param actionID is  MUST
     */
    Action (String actionID) {
        this(actionID,null);
    }
    /**
     * Constructor populate ActionList to create a list of actions to be executed in case of successfully executed current action.
     * @param actionList
     */
    Action (String actionID, ArrayList<IAction> actionList) {
        validateNextActions();
        this.nextActions.addAll(actionList);
        state = ActionState.INITIALIZED;
        setActionID(actionID);
    }

    /**
     * addActionList method keep adding one Action at a time to ActionList.
     *
     * @param action as object of Action class
     * @throws
     */
    public void addNext(IAction action) {
        validateNextActions();
        this.nextActions.add(action);
    };
    /**
     * addActionList method populates a list of next actions that have to be performed next.
     *
     * @param actionList as ArrayList of list of Action objects
     * @throws
     */
    public   void addNext(ArrayList<IAction> actionList) {
        // this.ActionList.addAll(actionList);
        // probably we need to evaluate Actions one by one to handle excpetions if any
        validateNextActions();
        this.nextActions.addAll(actionList);

    }
    abstract void removeNext(String actionId);

    public void addProperty(String key,Object value){
        this.addProperty(key,value);
    }
    public void removeProperty(String key) {
        this.removeProperty(key);
    }
    public Object getPropertyValue(String key){
        return properties.getProperty(key);
    };


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



    @Override
    public String toString() {

        // bases on the condition we may use reflection to create a toString output
        return this.toString();
    }



}
