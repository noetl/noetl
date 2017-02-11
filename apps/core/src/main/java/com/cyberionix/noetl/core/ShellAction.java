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
        setCommand(args);
    }

    public boolean ifCommand(){
        return this.getPropertyValue("CMD") == null ? false : true;
    }


    public String getCommand(){
        return this.getPropertyValue("CMD").toString();
    }

    public void setCommand(String ... args) {
        System.out.printf("ifcommad %b", ifCommand());
        if (ifCommand()) {
            StringBuilder builder = new StringBuilder();
            for (String arg : args) {
                if (builder.length() > 0) {
                    builder.append(" ");
                }
                this.addProperty("CMD", builder.append(arg).toString());
            }
            // else...? do we need to overwrite command arguments in case it was already defined?

        }
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
                ProcessBuilder exec = new ProcessBuilder((String) this.getPropertyValue("CMD"));
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
