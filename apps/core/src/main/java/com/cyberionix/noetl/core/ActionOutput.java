package com.cyberionix.noetl.core;

/**
 * Created by Davit on 01.26.2017.
 */
public class ActionOutput {
    private Object data = null;
    ActionOutput(Object data){
        this.data = data;
    }
    public String asText() {
        return data.toString();
    }

    public Object asObject() {
        return data;
    }

}
