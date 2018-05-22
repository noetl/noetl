package io.noetl.core
import com.typesafe.config._
import scala.collection.JavaConverters._
import scala.util.Try

//https://monix.io/docs/3x/eval/task.html

// In order to evaluate tasks, we'll need a Scheduler
import monix.execution.Scheduler.Implicits.global

// A Future type that is also Cancelable
import monix.execution.CancelableFuture

// Task is in monix.eval
import monix.eval.Task
import scala.util.{Success, Failure}

case class Workflow(
    name: String,
    displayName: String,
    description: String,
    start: List[String],
    variables: Config
)

object Workflow {
  def apply(config: Config): Workflow = config match {
    case config: Config =>
      new Workflow(
        name = config.getString("name"),
        displayName = config.getString("displayName"),
        description = config.getString("description"),
        start = config.getStringList("start").asScala.toList,
        variables = config.getConfig("variables"),
      )
    case _ => throw new IllegalArgumentException
  }
}

case class ActionFlow(workflow: Workflow, actions: Map[String, ActionConfig]) {
  def runFlow(): Unit = {
    println("Workflow's starting point => ", workflow.start)

    def findAction(actionName: String) = this.actions.get(actionName)

    def actionStartList = this.workflow.start.map(findAction)

    print("actionStartList " + actionStartList + " end!")
    //val a = Webservice("abc")
    //val b = Webservice("cde")
    //val c = Fork("xzf")
    //val seq = Seq(a,b,c)
    //seq.foreach(x => x.print)
  }

}

object ActionFlow {
  def apply(config: Config): ActionFlow = config match {
    case config: Config if config.hasPath(WORKFLOW) =>
      val workflow = Workflow(config.getConfig(WORKFLOW))
      val actionConfig = config.getConfig(WORKFLOW + "." + ACTIONS)
      val actionKeys = actionConfig.root().keySet().asScala
      println("List of actions names => " + actionKeys.mkString(" -> "))
      val actions = actionKeys map { actionId =>
        actionId -> ActionConfig(actionId, actionConfig.getConfig(actionId))
      }
      new ActionFlow(workflow, actions.toMap)
    case _ => throw new IllegalArgumentException
  }
}
