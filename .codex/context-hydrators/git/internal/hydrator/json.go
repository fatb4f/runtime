package hydrator

import (
	"encoding/json"
	"fmt"
)

// MarshalCanonical emits the one-line normalized JSON document used by the
// CLI and determinism properties. Struct field order and the canonically sorted
// occurrence list make the output byte-stable.
func MarshalCanonical(observation Observation) ([]byte, error) {
	if err := ValidateObservation(observation); err != nil {
		return nil, err
	}
	payload, err := json.Marshal(observation)
	if err != nil {
		return nil, fmt.Errorf("marshal committed snapshot observation: %w", err)
	}
	return append(payload, '\n'), nil
}
