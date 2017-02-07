package com.cyberionix.noetl.core;

import java.util.ArrayList;

import java.io.BufferedReader;
import java.io.InputStreamReader;
/**
 * Created by refugee on 2/6/17.
 */
public class ShellAction extends Action {

    ShellAction(String actionID){
        super(actionID);
    }

    ShellAction(String actionID, String ... args){
        super(actionID);
        this.addProperty("CMD", args);
    }

    public boolean ifCommand(){
        return (this.getPropertyValue("CMD") == null) ? false : true;
    }


    public String getCommand(String ... args){
        StringBuilder builder = new StringBuilder();
        for (String arg : args) {
            if (builder.length() > 0) {
                builder.append(" ");
            }
            builder.append(arg);
        }
        return builder.toString();
    }

    public void setCommand(String ... args) {
        if (ifCommand()) {
            this.addProperty("CMD", args);
        }
        // else...? do we need to overwrite command arguments in case it was already defined?

    }

    public void onStateChanged(Action action) {

    }

    @Override
    void myStateIsChanged() {

    }

    @Override
    void removeNext(String actionId) {

    }


    @Override
    void Execute() {
        if(ifCommand()) {
            try {
                ProcessBuilder exec = new ProcessBuilder(getCommand((String[]) this.getPropertyValue("CMD")));
                exec.redirectErrorStream(true);
                Process process = exec.start();
                BufferedReader stdout = new BufferedReader(new InputStreamReader(process.getInputStream()));
                while (stdout.readLine() != null) {
                    System.out.println(stdout);
                }
                setExitCode(process.waitFor());
                process.getInputStream().close();
            } catch (Exception e) {
                e.printStackTrace();
            }
        }

    }
}
