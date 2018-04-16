package io.noetl.core
import com.typesafe.config._

case class ActionFlow (noetldb: NoetlDb, actions: Map[String,ActionConfig])

object ActionFlow {
  def apply(noetldb: NoetlDb, config: Config ):  ActionFlow = (noetldb, config) match {
    case _ => new ActionFlow(noetldb, setActions(noetldb.main, config) )
  }

  def setActions(actionId: String, config: Config): Map[String, ActionConfig] = {

    Map(actionId -> ActionConfig(actionId,config.getConfig(actionId)))
  }

}
