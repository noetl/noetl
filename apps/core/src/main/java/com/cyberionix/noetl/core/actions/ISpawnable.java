package com.cyberionix.noetl.core.actions;

/**
 * Created by Davit on 02.14.2017.
 */
public interface ISpawnable extends IAction{
    public ISpawnable spawn();
    public ActionState getStateOf();
    public Integer getExitCodeOf();
    public ActionOutput getOutputResultOf();
    public Object getPropertyValueOf(String key);

    public int getIndex();
    public int getSpawnedCount();

}
