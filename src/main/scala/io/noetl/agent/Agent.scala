package io.noetl.agent

//import akka.stream.scaladsl.Framing
//import io.noetl.store.getConfig
//import pureconfig.loadConfig
//import com.typesafe.config.ConfigFactory
import pureconfig._
import java.nio.file.{Paths}
import io.noetl.util._

import scala.util.Try

object Agent {
  //import com.typesafe.config._
  // import pureconfig.loadConfig
  //val WORKFLOW = "workflow"
  //val ACTIONS = "actions"

  def main(args: Array[String]): Unit = {

    if (args.isEmpty)
      throw new IllegalArgumentException(
        s"Path for config file is not provided")

    val configPath = Try(args(0)).getOrElse(
      "src/main/resources/conf/tnotb-akuksin-xchg-rate-20180531.conf")


    implicit def hint[T] =
      ProductHint[T](ConfigFieldMapping(CamelCase, CamelCase))

    implicit val actionConfHint = new FieldCoproductHint[ActionConf]("type") {
      override def fieldValue(name: String) =  name.dropRight("Conf".length).toLowerCase
    }

    val workflowConfig =
      pureconfig.loadConfig[WorkflowConf](Paths.get(configPath)) match {
        case Right(conf) =>
          conf
        case Left(err) =>
          Console.err.println(err.toList)
          throw new Exception(err.head.description)
      }

    println(workflowConfig)

  }
}
