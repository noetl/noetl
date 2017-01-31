package com.cyberionix.noetl.core;

import org.junit.Test;

/**
 * Created by refugee on 1/28/17.
 */
public class WorkflowTest {
        @Test
        public void testMain() {
            System.out.println("workflow main method test");
            WorkflowBuilderJSON.main(new String[] {"/Users/refugee/projects/noetl/noetl/apps/core/src/main/resources/workflow1.json"});

//            assertEquals("onetwo", result);

        }
    }

