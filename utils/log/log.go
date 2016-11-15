package log

import (
	"encoding/json"

	"github.com/Sirupsen/logrus"
)

func JSONMessage(logger *logrus.Logger, formattedMessage string, data interface{}) {
	requestJSON, err := json.Marshal(data)
	if err != nil {
		logger.Fatal(err)
		return
	}
	logger.WithField("JSON", string(requestJSON)).Info(formattedMessage)
}
