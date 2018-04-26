package io.noetl

import java.nio.file.{FileSystems, Paths, Files} // http://tutorials.jenkov.com/java-nio/path.html
import com.typesafe.config._

package object store {

  def fs: String = FileSystems.getDefault.getSeparator

  def validateConfigPath (path: String ): String =  {
    if (!path.isEmpty && Files.exists(Paths.get(path)))
      path
    else {
      val currentDir = Paths.get(".")
      currentDir.toAbsolutePath + s"${fs}src${fs}main${fs}resources${fs}conf${fs}job1.conf"
    }

  }

  def getConfig(configPath: String): Config = {
    import java.io.File
    ConfigFactory.load(ConfigFactory.parseFile(new File(validateConfigPath(configPath))))
  }

}
