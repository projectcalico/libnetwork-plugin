package log

import (
	"encoding/json"

	logger "github.com/sirupsen/logrus"
)

func JSONMessage(formattedMessage string, data interface{}) {
	requestJSON, err := json.Marshal(data)
	if err != nil {
		logger.Fatal(err)
		return
	}
	logger.WithField("JSON", string(requestJSON)).Info(formattedMessage)
}
