package io.noetl.core

import com.typesafe.config._

import scala.util.Try
// http://www.scala-lang.org/api/2.12.0-M5/scala/collection/JavaConversions$.html - deprecated since 2.12. Use if need to downgrade to 2.8
import scala.collection.JavaConverters._
import ActionType._
import ActionState._

// some examples https://marcinkubala.wordpress.com/2013/10/09/typesafe-config-hocon/

case class ActionConfig (
 actionName: String,
 actionType: ActionType,
 actionRun: ActionRun
                  )


object ActionConfig {
  def apply(actionName: String, config: Config): ActionConfig = config match {
    case _ => new ActionConfig(
      actionName = actionName,
      actionType = ActionType(Try(config.getString("type")).getOrElse("action")),
      actionRun = ActionRun(config.getConfig("run"))
    )
  }
}

case class ActionFun(name: String, args: List[String])

object ActionFun {
  def apply(config: Config): ActionFun = config match
  {
    case _ => new ActionFun(config.getString("name"),config.getStringList("args").asScala.toList)
  }
}

case class ActionRunExit(code: String = "0", message: String = "" )

case class ActionRun(
                      when: List[String] = List.empty[String],
                      after: List[String] = List.empty[String],
                      state: ActionState,
                      message: String = "waiting for start",
                      next: List[String] = List.empty[String],
                      exit: ActionRunExit = ActionRunExit(),
                      fun: ActionFun
                    )

object ActionRun {
  def apply(config: Config): ActionRun = config match
  {
    case _ => new ActionRun(
      Try(config.getStringList("when").asScala.toList).getOrElse(List.empty[String]),
      Try(config.getStringList("after").asScala.toList).getOrElse(List.empty[String]),
      ActionState(Try(config.getString("state")).getOrElse("unknown")),
      Try(config.getString("message")).getOrElse("waiting for start"),
      Try(config.getStringList("next").asScala.toList).getOrElse(List.empty[String]),
      ActionRunExit(),
      ActionFun(config.getConfig("fun"))
    )
  }
}
