package com.cyberionix.noetl.core.actions;

import java.util.*;

/**
 * Created by refugee on 1/24/17.
 */

public abstract class Action implements IAction,Cloneable,Runnable{

    /* declarative part */
    private String actionType; //e.g. CLI,DB,REST...
    private String actionID; //must be unique among all action in workflow
    private String name;
    private String description;
    private Properties properties;

    //private HashMap<String,Action> next;
    private List<ISpawnable> nextActions;

    /* processing part */
    private Integer exitCode = null;
    private ActionState state = ActionState.ONHOLD;
    private ActionOutput outputResult = null;

    private Thread actionThread = null; // thinking of  use some Thread pool

    private ArrayList<ISpawnable> instances = new ArrayList(1);




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
            this.nextActions = new ArrayList<ISpawnable>();
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
       // this(actionID,null);
        this.actionID = actionID;
    }
    /**
     * Constructor populate ActionList to create a list of actions to be executed in case of successfully executed current action.
     * @param actionList
     */
    Action (String actionID, ArrayList<ISpawnable> actionList) {
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
    public void addNext(ISpawnable action) {
        validateNextActions();
        this.nextActions.add(action);
    };
    /**
     * addActionList method populates a list of next actions that have to be performed next.
     *
     * @param actionList as ArrayList of list of Action objects
     * @throws
     */
    public   void addNext(ArrayList<ISpawnable> actionList) {
        // this.ActionList.addAll(actionList);
        // probably we need to evaluate Actions one by one to handle excpetions if any
        validateNextActions();
        this.nextActions.addAll(actionList);

    }
    abstract void removeNext(String actionId);

    public void addProperty(String key,String value){
        if (properties == null) {
            properties = new Properties();
        }
        properties.setProperty(key,value);
    }
    public void removeProperty(String key) {
        if (properties != null) {
            this.removeProperty(key);
        }
    }
    public Object getPropertyValue(String key){
        System.out.printf("getPropertyValue %s",key);
        if (properties == null || !properties.containsKey(key)) {
            return null;
        } else {
            return properties.getProperty(key);
        }

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


    @Override
    public String toString() {

        // bases on the condition we may use reflection to create a toString output
        return this.toString();
    }

    @Override
    public Object clone() throws CloneNotSupportedException {
        return super.clone();
    }




   // ###############   Main Logic part ###############

    protected void informStateIsChanged(){ //here nexts should be informed
        /*
        here we must be shure that according spawned object of nextAction's item exists or create it.
         How to bind? When to use spawn
         */
        for (ISpawnable act: nextActions) {
            act.spawn().onStateChanged(this); //this is not corrects
        }
    };

    public void onStateChanged(IAction predecessorAction){
        /* template */
        if (predecessorAction.getState() == ActionState.FINISHED && predecessorAction.getExitCode() == 0) {
            (actionThread = new Thread(this)).start();
        }
    };

    public ISpawnable spawn() { // add new instance
        Action newActionInstance = null;
        try {
            newActionInstance = (Action)this.clone();//How does this will work with inheritance
            newActionInstance.setActionID(this.actionID+UUID.randomUUID());//or use +this.instances.size()

            instances.add((ISpawnable)newActionInstance);

        } catch (CloneNotSupportedException e) {
            e.printStackTrace();
        } finally {
            return (ISpawnable)newActionInstance;
        }
        
    };



    public void run(){
        informStateIsChanged();
        /* threading is to be defined by some attributes or argument*/
        /* do some job */
    };

    public void run(String[] args) {
        // type of "args" argument is to discuss. String[] is just stub
        // initialize action. args supposed to be used in this section
        (actionThread = new Thread(this)).start();
    }







}
