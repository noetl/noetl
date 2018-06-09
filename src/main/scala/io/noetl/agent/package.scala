package io.noetl

import java.nio.file.Paths

import pureconfig.{
  CamelCase,
  ConfigFieldMapping,
  FieldCoproductHint,
  ProductHint
}

package agent {

  sealed trait ActionState

}

package object agent {

  /**
    * https://pureconfig.github.io/docs/overriding-behavior-for-case-classes.html
    *
    * PureConfig provides a way to create a ConfigFieldMapping by defining the naming conventions of the fields in the
    * Scala object and in the configuration file. Some of the most used naming conventions are supported directly in
    * the library:
    *
    * CamelCase (examples: camelCase, useMorePureconfig);
    * SnakeCase (examples: snake_case, use_more_pureconfig);
    * KebabCase: (examples: kebab-case, use-more-pureconfig);
    * PascalCase: (examples: PascalCase, UseMorePureconfig).
    */
  implicit def hint[T] =
    ProductHint[T](ConfigFieldMapping(CamelCase, CamelCase))

  /**
    * https://pureconfig.github.io/docs/overriding-behavior-for-sealed-families.html
    *
    * FieldCoproductHint can also be adapted to write class names in a different ways.
    *
    */
  implicit val actionConfHint = new FieldCoproductHint[ActionConf]("type") {
    override def fieldValue(name: String) =
      name.dropRight("Conf".length).toLowerCase
  }

  def validateWorkflowConfig(configPath: String): WorkflowConf =
    pureconfig.loadConfig[WorkflowConf](Paths.get(configPath)) match {
      case Right(conf) => conf
      case Left(err) =>
        Console.err.println(err.toList)
        throw new Exception(err.head.description)
    }

}
