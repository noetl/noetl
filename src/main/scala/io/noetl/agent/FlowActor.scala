package io.noetl.agent

import akka.actor.{Actor, ActorRef, Props}
import io.noetl.agent.actions.SellActionActor
import io.noetl.util.getCurrentTime

object FlowActor {

  case class InitActions()

  case class Start()

  case class Stop()

}

class FlowActor(workflowConfig: WorkflowConf) extends Actor {

  import FlowActor._

  private def actionsOf(workflowConfig: WorkflowConf): Map[String, ActorRef] = {
    workflowConfig.actions.map({
      case (actionKey, actionConf) => {
        actionKey -> actionOf(actionKey, actionConf)
      }
    })
  }

  private def actionOf(actionKey: String, actionConf: ActionConf): ActorRef = {
    actionConf match {
      case conf: ShellConf => context.actorOf(Props(new SellActionActor(conf)), actionKey)
      // todo case conf: AnyActionConf => context.actorOf(Props(new AnyActionActor(conf)), actionKey)
    }
  }

  override def receive: Receive = {
    updated(actionsOf(workflowConfig))
  }

  private def updated(actionsRef: Map[String, ActorRef]): Receive = {
    case Start => {
      println(s"$getCurrentTime start flow Thread name ${Thread.currentThread().getName}")
      workflowConfig.start.foreach(actionKey => {
        actionsRef(actionKey) ! TryStart
      })
    }
    case Stop => {
      context.actorSelection("./*") ! Stop // todo need by thinking
    }
  }
}
