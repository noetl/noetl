package io.noetl.core

import com.typesafe.config._
import scala.util.Try
import scala.collection.JavaConverters._

sealed trait ActionType

case object Workflow extends ActionType
case object Task extends ActionType
case object Step extends ActionType

case class Action (
 actionName: String,
 actionType: ActionType,
 actionRun: ActionRun
                  )


object Action {
  def apply(config: Config): Action = config match {
    case _ => new Action(
      actionName = config.getString("name"),
      actionType = setActionType(config.getString("type")),
      actionRun = ActionRun(config.getConfig("run"))
    )
  }
  def setActionType(actionType: String): ActionType = actionType match {
    case "workflow" => Workflow
    case "task" => Task
    case _ => Step
  }
}
