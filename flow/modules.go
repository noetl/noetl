package flow

import (
	"context"
	"noetl/workflows"

	"cloud.google.com/go/pubsub"
	"github.com/golang/glog"
	"golang.org/x/oauth2/google"
	"google.golang.org/api/option"
)

func s3(v interface{}, ctx map[string]interface{}) (string, error) {
	m := v.(map[string]interface{})
	module := workflows.S3{}
	var accessKey string
	var secretKey string
	if action, ok := m["action"].(string); ok {
		module.Action = action
	}
	if path, ok := m["path"].(string); ok {
		module.Path = path
	}
	if validate, ok := m["validate"].(string); ok {
		module.Validate = validate
	}
	if accKey, ok := ctx["access-key"]; ok {
		accessKey = accKey.(string)
	}
	if sKey, ok := ctx["secret-key"]; ok {
		secretKey = sKey.(string)
	}

	glog.V(3).Infoln("process s3 module")
	glog.Infof("access: %v, secret: %v", accessKey, secretKey)

	gctx := context.Background()
	creds, err := google.CredentialsFromJSON(gctx, []byte("JSON creds"), pubsub.ScopePubSub)
	if err != nil {
		// TODO: handle error.
	}
	client, err := pubsub.NewClient(gctx, "project-id", option.WithCredentials(creds))
	if err != nil {
		// TODO: handle error.
	}
	_ = client // Use the client.

	// gctx := context.Background()
	// // client, err := storage.NewClient(gctx)
	// // if err != nil {
	// // 	// TODO: Handle error.
	// // }
	// client, err := storage.NewClient(gctx, option.WithoutAuthentication())
	// if err != nil {
	// 	glog.Fatalln(err)
	// }
	// bkt := client.Bucket("noetl")
	// obj := bkt.Object("data")
	// w := obj.NewWriter(gctx)
	// // Write some text to obj. This will either create the object or overwrite whatever is there already.
	// if _, err := fmt.Fprintf(w, "This object contains text.\n"); err != nil {
	// 	glog.Fatalln(err)
	// }
	// // Close, just like writing a file.
	// if err := w.Close(); err != nil {
	// 	glog.Fatalln(err)
	// }

	return "", nil
}

func rest(v interface{}, ctx map[string]interface{}) (string, error) {
	glog.V(3).Infoln("process rest module")
	return "", nil
}

func aggregate(v interface{}, ctx map[string]interface{}) (string, error) {
	glog.V(3).Infoln("process aggregate module")
	return "", nil
}
