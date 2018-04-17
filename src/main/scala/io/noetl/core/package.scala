package io.noetl

package core {

  import com.typesafe.config._
  import scala.util.Try
  import scala.collection.JavaConverters._



  case class NoetlDb (name: String, host: String, home: String, path: String, file: String, main: String)

  object NoetlDb {
    def apply(config: Config): NoetlDb = config match {
      case config: Config => new NoetlDb(
        name = config.getString("name"),
        host = config.getString("host"),
        home = config.getString("home"),
        path = config.getString("path"),
        file = config.getString("file") ,
        main = config.getString("main")
      )
      case _ => throw new IllegalArgumentException
    }
  }

}

package object core {
  val NOETLDB = "noetldb"
  val ACTIONS = "actions"
}