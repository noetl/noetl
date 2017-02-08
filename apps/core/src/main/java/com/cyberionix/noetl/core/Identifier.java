package com.cyberionix.noetl.core;

/**
 * Created by refugee on 2/7/17.
 *
 * Identifier interface to be implemented for Action and workflow IDs
 *
 */


public interface Identifier<T> {
    public <T> T getID();
}
