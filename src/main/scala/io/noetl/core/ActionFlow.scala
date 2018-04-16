package io.noetl.core
import com.typesafe.config._

case class ActionFlow (noetldb: NoetlDb, actions: Map[String,Action])

object ActionFlow {
  def apply(noetldb: NoetlDb, config: Config ):  ActionFlow = config match {
    case _ => new ActionFlow(noetldb, setActions(noetldb.main, config) )
  }

  def setActions(actionId: String, config: Config): Map[String, Action] = {

    Map(actionId -> Action(config.getConfig(actionId)))

  }

}
