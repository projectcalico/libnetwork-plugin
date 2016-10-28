package log

import (
	"encoding/json"
	"log"
)

func JSONMessage(logger *log.Logger, formattedMessage string, data interface{}) {
	requestJSON, err := json.Marshal(data)
	if err != nil {
		logger.Fatal(err)
		return
	}
	logger.Printf(formattedMessage, string(requestJSON))
}
