package com.cyberionix.noetl.core;

import org.junit.Assert;
import org.junit.Before;
import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;

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
