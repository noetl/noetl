package io.noetl.agent

import scala.io.StdIn
import akka.actor.{ActorSystem, Props}

import io.noetl.agent.FlowActor.Start

object Agent {

  def main(args: Array[String]): Unit = {
    println(s"MEIN Thread name ${Thread.currentThread().getName}")
    val system = ActorSystem("noetl")

    val configPath = "src/main/resources/conf/sergey-agent-conf-prototype-20180720.conf"
    val workflowConfig = parseWorkflowConfigWithFile(configPath)
    val flowInstance = system.actorOf(Props(new FlowActor(workflowConfig)), "templateconfigname-instance-1")

    flowInstance ! Start

    println(s"Press RETURN to stop...")
    StdIn.readBoolean()
    println(s"exit")
  }
}
