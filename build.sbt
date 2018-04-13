name := "noetl"

version := "1.0"

scalaVersion := "2.12.4"

libraryDependencies ++= Seq(
  "com.typesafe.scala-logging" %% "scala-logging" % "3.8.0",
  "org.slf4j" % "slf4j-api" % "1.7.25",
  "org.slf4j" % "log4j-over-slf4j" % "1.7.25",
  "ch.qos.logback" % "logback-classic" % "1.2.3",
  "org.apache.httpcomponents" % "httpclient" % "4.5.3",
  "org.apache.httpcomponents" % "httpasyncclient" % "4.1.3",
  "org.json4s" %% "json4s-jackson" % "3.5.3",
  "com.typesafe" % "config" % "1.3.3"
)