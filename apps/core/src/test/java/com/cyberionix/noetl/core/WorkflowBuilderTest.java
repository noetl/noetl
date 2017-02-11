package com.cyberionix.noetl.core;

import com.cyberionix.noetl.core.actions.ShellAction;
import org.junit.Assert;
import org.junit.Before;
import org.junit.Test;

/**
 * Created by refugee on 2/7/17.
 */
public class WorkflowBuilderTest {

    WorkflowBuilder workflow;

    @Before
    public void setUpWorkflow()
    {
        String[] cmdargs = {"ls","-","l"};
        ShellAction shellAction = new ShellAction("start");
        shellAction.setCommand(cmdargs);
        workflow = new WorkflowBuilder(shellAction);
    }

    @Test
    public void testWorkflow()
    {
        Assert.assertEquals( "Workflow start name",
                "start",
                workflow.getStartID() );
    }

}
