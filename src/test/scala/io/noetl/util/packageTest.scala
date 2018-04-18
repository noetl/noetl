package io.noetl.util

import org.scalatest.{FlatSpec, Matchers}
import org.scalatest.exceptions.TestFailedException
import java.util.UUID

package object packageTest extends FlatSpec with Matchers {

  info("Testing strip")

  "strip" should "work" in {
    val stripped = strip(s"""strip1\nand\rstrip test""")
    println(stripped)
    assert(stripped === "strip1 and strip test")
    stripped match {
      case x: String => println("Passed")
      case "strip1 and strip test" => println("strip test is passed")
      case _ => println("strip is failed")
    }
  }

  info("Testing getUuid")
  "getUuid" should "display values " in {

    val uuidVal = getUuid("00000000-3be7-a2b4-0000-00003be7a2b4")
    assert(UUID.fromString("00000000-3be7-a2b4-0000-00003be7a2b4") === uuidVal)

    val regExp = "[0-9]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}".r
    println("uuidVal =" + uuidVal)
    uuidVal.toString match {
      case regExp(s) => println("UUID Regexp match")
      case _ => println("UUID is not  matching")
    }

    info("Testing Exception for getUuid")
    intercept[TestFailedException] {
      assert(uuidVal === "00000000-3be7-a2b4-0000-00003be7a2b4")
    }
  }


} // end of package object packageTest
