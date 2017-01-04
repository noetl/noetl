var mongoose = require('mongoose');
var Schema = mongoose.Schema;


//noinspection JSAnnotator
var Document = new Schema({
    mainField: {
        type: String,
        default: "Some Field"
    },
    mainField2: {
        type: String,
        trim: true,
        unique: true,
        required: true
    },
    extra:{
        extra_field: String,
        extra_field2:[{
            extra_field_sub:String
        }]
    }
});

var Universal = new Schema({
    document: Document,
    postedBy: {
        type: mongoose.Schema.Types.ObjectId,
        ref: 'User'
    }
}, {timestamps: true});


module.exports = mongoose.model('Universal', Universal);