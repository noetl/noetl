package io.noetl

import java.nio.file.Paths
package agent {

  sealed trait Status
  case object Pending extends Status
  case object Processing extends Status
  case object Finished extends Status
  case object Failed extends Status

  case class TryStart()
}

package object agent {

  import PureconfigHoconSettings._

  def parseWorkflowConfigWithFile(configPath: String): WorkflowConf =
    pureconfig.loadConfig[WorkflowConf](Paths.get(configPath)) match {
      case Right(conf) => conf
      case Left(err) =>
        err.toList.foreach(e => Console.err.println(e))
        throw new Exception(err.head.description)
    }

}
