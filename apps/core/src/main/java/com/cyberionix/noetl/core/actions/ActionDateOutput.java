package com.cyberionix.noetl.core.actions;

import java.time.LocalDateTime;

/**
 * Created by Davit on 01.26.2017.
 */
public class ActionDateOutput extends ActionOutput {
    public ActionDateOutput(LocalDateTime data) {
        super(data);
    }

    public LocalDateTime asDate() {
        return (LocalDateTime)this.asObject();
    }
}
