package io.noetl

import org.scalatest._

class HelloSpec extends FlatSpec with Matchers {
  "Math" should "work" in {
    (1 + 1) should be(2)
  }
}
