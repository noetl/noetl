package com.cyberionix.noetl.core;

import com.cyberionix.noetl.core.actions.IAction;

/**
 * Created by refugee on 2/7/17.
 */
public class WorkflowBuilder extends Workflow {

//    WorkflowBuilder (String actionID, IAction action) {
//        super(action);
//    }

    WorkflowBuilder (IAction action) {
        super(action);
    }

    @Override
    void addProperty(String key, String value) {

    }

    @Override
    public void Execute() {

    }

    @Override
    void removeProperty(String key) {

    }

    @Override
    void getActionOutput(String key) {

    }


}
