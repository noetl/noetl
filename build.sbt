import Dependencies._

lazy val root = (project in file("."))
  .enablePlugins(BuildInfoPlugin)
  .settings(commonSettings ++ buildInfoSettings)

lazy val commonSettings = Seq(
  organization := "io.noetl",
  scalaVersion := "2.12.4",
  version := "1.0",
  name := "noetl",
  resolvers ++= projectResolvers,
  libraryDependencies ++= dependencies,
  scalacOptions ++= compileSettings,
  scalafmtOnCompile := true,
  fork in run := true,
  fork in Test := true,
  fork in testOnly := true,
  connectInput in run := true,
  javaOptions in run ++= forkedJvmOption,
  javaOptions in Test ++= forkedJvmOption,
  javaOptions in Universal ++= Seq(
    "-server",
    "-Dfile.encoding=UTF8",
    "-Duser.timezone=UTC",
    "-Dpidfile.path=/dev/null",
    "-J-Xss1m",
    "-J-XX:+CMSClassUnloadingEnabled",
    "-J-XX:ReservedCodeCacheSize=256m",
    "-J-XX:+DoEscapeAnalysis",
    "-J-XX:+UseConcMarkSweepGC",
    "-J-XX:+UseParNewGC",
    "-J-XX:+UseCodeCacheFlushing",
    "-J-XX:+UseCompressedOops"
  )
)

lazy val compileSettings = Seq(
  "-encoding",
  "UTF-8",
  "-unchecked",
  "-deprecation",
  "-feature",
  "-language:_",
  "-target:jvm-1.8",
  "-unchecked",
  "-Ydelambdafy:method",
  "-Ywarn-adapted-args",
  "-Ywarn-dead-code",
  "-Ywarn-inaccessible",
  "-Ywarn-numeric-widen",
  "-Ywarn-unused-import",
  "-Ywarn-value-discard",
  "-Ywarn-nullary-override",
  "-Ywarn-nullary-unit",
  "-Xlog-free-terms",
  "-Xlint:adapted-args", // warn if an argument list is modified to match the receiver
  "-Xlint:nullary-unit", // warn when nullary methods return Unit
  "-Xlint:inaccessible", // warn about inaccessible types in method signatures
  "-Xlint:nullary-override", // warn when non-nullary `def f()' overrides nullary `def f'
  "-Xlint:infer-any", // warn when a type argument is inferred to be `Any`
  "-Xlint:-missing-interpolator", // disables missing interpolator warning
  "-Xlint:doc-detached", // a ScalaDoc comment appears to be detached from its element
  "-Xlint:private-shadow", // a private field (or class parameter) shadows a superclass field
  "-Xlint:type-parameter-shadow", // a local type parameter shadows a type already in scope
  "-Xlint:poly-implicit-overload", // parameterized overloaded implicit methods are not visible as view bounds
  "-Xlint:option-implicit", // Option.apply used implicit view
  "-Xlint:delayedinit-select", // Selecting member of DelayedInit
  "-Xlint:by-name-right-associative", // By-name parameter of right associative operator
  "-Xlint:package-object-classes", // Class or object defined in package object
  "-Xlint:unsound-match" // Pattern match may not be typesafe
)

lazy val forkedJvmOption = Seq(
  "-server",
  "-Dfile.encoding=UTF8",
  "-Duser.timezone=UTC",
  "-Xss1m",
  "-Xms2048m",
  "-Xmx2048m",
  "-XX:+CMSClassUnloadingEnabled",
  "-XX:ReservedCodeCacheSize=256m",
  "-XX:+DoEscapeAnalysis",
  "-XX:+UseConcMarkSweepGC",
  "-XX:+UseParNewGC",
  "-XX:+UseCodeCacheFlushing",
  "-XX:+UseCompressedOops"
)

lazy val buildInfoSettings = Seq(
  buildInfoKeys := Seq[BuildInfoKey](name, version, scalaVersion, sbtVersion),
  buildInfoPackage := "noetl",
  buildInfoOptions += BuildInfoOption.ToJson,
  buildInfoOptions += BuildInfoOption.BuildTime
)
