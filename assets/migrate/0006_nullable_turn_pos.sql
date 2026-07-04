-- Make rooms.turn_pos nullable: NULL indicates the room is IDLE (no current speaker).
ALTER TABLE rooms DROP COLUMN turn_pos;
ALTER TABLE rooms ADD COLUMN turn_pos INTEGER DEFAULT NULL;
