package io.noetl

import java.sql._
import java.util.UUID
import com.typesafe.scalalogging.LazyLogging
import scala.reflect.ClassTag

package object util extends LazyLogging {

  def strip(str: String): String = {
    str.stripMargin.replaceAll("\r|\n", " ")
  }

  def toCamelCase(s: String) = {
    val l = s.replaceAll("'|`", "") split ("[\\W_]+|(?<=[a-z])(?=[A-Z][a-z])") map (_.toLowerCase)
    l(0) + l.tail.map(_.capitalize).mkString
  }

  /**
    * @return converts Option[java.util.date] or Option[java.sql.Date] to Option[java.sql.Timestamp].
    * @param date Option[java.util.Date].
    */
  def convertDate(date: Option[_]): Option[java.sql.Timestamp] = date match {
    case None => None
    case x =>
      val dt = x.get
      dt match {
        case dt: java.sql.Timestamp => Option(dt)
        case dt: java.sql.Date      => Option(new java.sql.Timestamp(dt.getTime))
        case dt: java.util.Date     => Option(new java.sql.Timestamp(dt.getTime))
        case _                      => None
      }
  }

  /*
   * filter out all characters lower in value then space
   * NUL,SOH,STX,ETX,EOT,ENQ,ACK,BEL,BS,TAB,LF,VT,FF,CR,SO,SI,DLE,DC1,DC2,DC3,DC4,NAK,SYN,ETB,CAN,EM,SUB,ESC,FS,GS,RS,US
   */
  def replaceControlCharacters(str: String): String =
    str.toString.filter(_ >= ' ')

  def replaceControlCharacters(str: Option[String]): Option[String] =
    str match {
      case Some(str) =>
        Option[String] {
          str map {
            case 0       => "{{NUL}}"
            case 1       => "{{SOH}}"
            case 2       => "{{STX}}"
            case 3       => "{{ETX}}"
            case 4       => "{{EOT}}"
            case 5       => "{{ENQ}}"
            case 6       => "{{ACK}}"
            case 7       => "{{BEL}}"
            case 8       => "{{BS}}"
            case 9       => "{{TAB}}"
            case 10      => "{{LF}}"
            case 11      => "{{VT}}"
            case 12      => "{{FF}}"
            case 13      => "{{CR}}"
            case anyChar => anyChar
          } mkString
        }
      case None => None
    }

  def getUuid(uuid: String): UUID = UUID.fromString(uuid)

  def uuid2long(uuid: UUID): Long = uuid.getLeastSignificantBits

  def uuid2long(uuid: String): Long = getUuid(uuid).getLeastSignificantBits

  def getStringUuid(id: Long): String = new UUID(id, id).toString

  def getStringUuid(id: String): String = {
    val idLong = id.replaceAll("^\'|\'$", "").toLong
    new UUID(idLong, idLong).toString
  }

  def getClassTag[T](v: T)(implicit o: ClassTag[T]): String = o.toString

  def by[Closeable <: { def close(): Unit }, B](closeable: Closeable)(
      getB: Closeable => B): B =
    try {
      getB(closeable)
    } finally {
      closeable.close()
    }

  def query[B](connection: Connection, sql: String)(
      process: ResultSet => B): B =
    by(connection) { connection =>
      by(connection.createStatement) { statement =>
        by(statement.executeQuery(sql)) { results =>
          process(results)
        }
      }
    }

  def collect[T](test: => Boolean)(block: => T): List[T] = {
    import scala.collection.mutable.ListBuffer
    val ret = new ListBuffer[T]
    while (test) ret += block
    ret.toList
  }

  def run[T](connection: Connection, sql: String)(
      process: ResultSet => T): List[T] =
    query(connection, sql) { results =>
      collect(results.next) {
        process(results)
      }
    }

  def executeJdbcUpdate(url: String,
                        username: String,
                        password: String,
                        sqlUpdate: String,
                        driver: String = "com.mysql.jdbc.Driver"): Unit = {
    Class.forName(driver)
    val connection = DriverManager.getConnection(url, username, password)
    try {
      val exec = connection.createStatement()
      exec.executeUpdate(sqlUpdate)
      ()
    } catch {
      case e: SQLException =>
        logger.error(
          s"execute Jdbc Update url: $url \n query: $sqlUpdate \n error message $e")
    } finally {
      connection.close()
    }

  }

  def executeJdbcStoreProc(url: String,
                           username: String,
                           password: String,
                           cmd: String,
                           driver: String = "com.mysql.jdbc.Driver"): Unit = {
    Class.forName(driver)
    val connection = DriverManager.getConnection(url, username, password)
    try {
      val exec: CallableStatement = connection.prepareCall(cmd)
      val rs = exec.execute()
      logger.info(s"executed {}", rs.toString)
    } catch {
      case e: SQLException =>
        logger.error(
          s"execute Jdbc Store Proc url: $url \n query cmd: $cmd \n error message $e")
    } finally {
      connection.close()
    }
  }
}
