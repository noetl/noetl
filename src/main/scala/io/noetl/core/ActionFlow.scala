package io.noetl.core
import com.typesafe.config._
import scala.collection.JavaConverters._
import scala.util.Try



case class Workflow (
                      name: String,
                      displayName: String,
                      description: String,
                      start: List[String],
                      variables: Config
                    )

object Workflow {
  def apply(config: Config): Workflow = config match {
    case config: Config => new Workflow(
      name = config.getString("name"),
      displayName = config.getString("displayName"),
      description = config.getString("description"),
      start = config.getStringList("start").asScala.toList,
      variables = config.getConfig("variables"),
      )
    case _ => throw new IllegalArgumentException
  }
}

case class ActionFlow (workflow: Workflow, actions: Map[String,ActionConfig])

object ActionFlow {
  def apply(config: Config ):  ActionFlow = config match {
    case  config: Config if config.hasPath(WORKFLOW) =>
      val workflow = Workflow(config.getConfig(WORKFLOW))
      val actionConfig = config.getConfig(WORKFLOW + "." + ACTIONS)
      val actionKeys = actionConfig.root().keySet().asScala
      println("List of actions names => " + actionKeys.mkString(" -> "))
      val actions = actionKeys map {
        actionId => actionId -> ActionConfig(actionId, actionConfig.getConfig(actionId))
      }
      new ActionFlow(workflow, actions.toMap )
    case _ => throw new IllegalArgumentException
  }
}
