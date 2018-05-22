package io.noetl.core

import io.noetl.store._
import scala.util.Try
import akka.stream.scaladsl.Framing // {JsonFraming, Source, Flow, Tcp}
// import akka.util.ByteString

object Agent {

  def main(args: Array[String]): Unit = {

    if (args.isEmpty)
      throw new IllegalArgumentException(
        s"Path for config file is not provided")

    val configPath = Try(args(0)).getOrElse("")

    val config = configKeyExists("workflow", getConfig(configPath))

    val actionFlow = ActionFlow(config)

    println("Framing action flow: ", Framing.formatted(actionFlow.toString))

    actionFlow.runFlow()
  }

}
