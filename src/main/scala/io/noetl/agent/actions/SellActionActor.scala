package io.noetl.agent.actions

import akka.actor.{Actor, Status}
import io.noetl.agent._
import io.noetl.util.getCurrentTime
import scala.concurrent.Future
import scala.concurrent.ExecutionContext.Implicits.global
import akka.pattern.pipe
import SellActionActor._

object SellActionActor {
  case class UpdateSubscribedActionStatus(name: String, status: Status)
  case class SellActionState(status: Status, canSendMessage: List[String], subscribedStatuses: Map[String, Status])
  case class SellTaskResult[T](result: T)
  case class SellTaskFailure[T](error: T)
}
class SellActionActor(conf: ShellConf) extends Actor {

  private val actorName = self.path.name

  private def task(): Future[SellTaskResult[Int]] = {
    Future({
      println(s"$getCurrentTime start $actorName Thread name ${Thread.currentThread().getName}")
      Thread sleep 5000
      conf.shellScript.foreach(commandLine => println(s"$getCurrentTime $commandLine"))
      println(s"$getCurrentTime finished $actorName Thread name ${Thread.currentThread().getName}")
      SellTaskResult(300)
    })
  }

  private def initState(conf: ShellConf): SellActionState = {
    SellActionState(Pending, canSendMessage = List.empty ++ conf.subscribers, Map(conf.runDependencies.map { s => (s.actionKey, Pending) }: _*)) // todo implement requirementsForStart handler
  }

  override def receive: Receive = {
    updated(initState(conf))
  }

  private def canIStart(state: SellActionState): Boolean = {
    val isSubscribedFinished = state.subscribedStatuses.filter(value => {
      value._2 != Finished
    }).isEmpty
    val isFirstActionInBranch = state.subscribedStatuses.isEmpty
    val isValidDependency = isSubscribedFinished && (state.status == Pending)
    isValidDependency || isFirstActionInBranch
  }

  private def sendStatusToSubscribers(state: SellActionState, status: Status): Unit = {
    state.canSendMessage.foreach(actionNameValue => {
      context.actorSelection(s"../$actionNameValue") ! UpdateSubscribedActionStatus(actorName, status)
    })
  }

  private def tryStartTask(state: SellActionState): Unit = {
    if (canIStart(state)) {
      task().pipeTo(self)
    }
  }

  private def updated(actionState: SellActionState): Receive = {
    case UpdateSubscribedActionStatus(name, status) => {
      if (actionState.subscribedStatuses.contains(name)) {
        val state = actionState.copy(subscribedStatuses = actionState.subscribedStatuses + (name -> status)) // todo Create reducers for change behavior
        context.become(updated(state))
        tryStartTask(state)
      }
    }
    case SellTaskResult(a) => {
      context.become(updated(actionState.copy(status = Finished)))
      sendStatusToSubscribers(actionState, Finished)
    }
    case Status.Failure(error) => {
      println(s"$getCurrentTime TaskFailure $error in actor $actorName ${Thread.currentThread().getName}")
      context.become(updated(actionState.copy(status = Failed)))
      sendStatusToSubscribers(actionState, Failed)
    }
    case TryStart => {
      tryStartTask(actionState)
    }
    case any => {
      println(s"$getCurrentTime not support message $any in actor $actorName ${Thread.currentThread().getName}")
    }
  }
}
