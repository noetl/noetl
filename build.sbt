name := "noetl"

version := "1.0"

scalaVersion := "2.12.4"

lazy val scalaTestVersion = "3.0.5"

lazy val scalaCheckVersion = "1.13.5"

/*  http://www.scalatest.org
 *  1. Add the plug-in in build.sbt:
 *  addSbtPlugin("com.artima.supersafe" % "sbtplugin" % "1.1.2")
 *   Do not add the above plug-in anywhere else
 *  2.  Add to ~/.sbt/0.13/global.sbt
 *  resolvers += "Artima Maven Repository" at "http://repo.artima.com/releases"
 *  Do not add this resolver anywhere else
 *  Make sure you have an empty line before and after each of the sbt lines
*/

libraryDependencies ++= Seq(
  "com.typesafe.scala-logging" %% "scala-logging" % "3.8.0",
  "org.scalactic" %% "scalactic" % "3.0.5",
  "org.scalatest" %% "scalatest" % "3.0.5" % "test",
  "org.slf4j" % "slf4j-api" % "1.7.25",
  "org.slf4j" % "log4j-over-slf4j" % "1.7.25",
  "ch.qos.logback" % "logback-classic" % "1.2.3",
  "org.apache.httpcomponents" % "httpclient" % "4.5.3",
  "org.apache.httpcomponents" % "httpasyncclient" % "4.1.3",
  "org.json4s" %% "json4s-jackson" % "3.5.3",
  "com.typesafe" % "config" % "1.3.3"
)

logBuffered in Test := false

