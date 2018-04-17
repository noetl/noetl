package io.noetl.core
import com.typesafe.config._
import scala.collection.JavaConverters._

case class ActionFlow (noetlDb: NoetlDb, actions: Map[String,ActionConfig])

object ActionFlow {
  def apply(config: Config ):  ActionFlow = config match {
    case  config: Config if config.hasPath(NOETLDB) && config.hasPath(ACTIONS) =>
      val noetlDb = NoetlDb(config.getConfig(NOETLDB))
      val actionConfig = config.getConfig(ACTIONS)
      val actionKeys = actionConfig.root().keySet().asScala
      val actions = actionKeys map {
        actionId => actionId -> ActionConfig(actionId, actionConfig.getConfig(actionId))
      }
      new ActionFlow(noetlDb, actions.toMap )
    case _ => throw new IllegalArgumentException
  }
}
