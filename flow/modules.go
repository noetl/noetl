package flow

import (
	"github.com/golang/glog"
)

func s3(v interface{}) (string, error) {
	glog.V(3).Infoln("process s3 module")
	return "", nil
}

func rest(v interface{}) (string, error) {
	glog.V(3).Infoln("process rest module")
	return "", nil
}

func aggregate(v interface{}) (string, error) {
	glog.V(3).Infoln("process aggregate module")
	return "", nil
}
