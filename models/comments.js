var mongoose = require('mongoose');
var Schema = mongoose.Schema;

var Comment = new Schema({

    document: {
        type: mongoose.Schema.Types.ObjectId,
        required: true,
        ref: 'Universal'
    },
    postedBy: {
        type: mongoose.Schema.Types.ObjectId,
        ref: 'User'
    },
    text: {
        type: String,
        required: true
    },
    public: {
        type: Boolean,
        default: true
    }
    
}, {timestamps: true});


module.exports = mongoose.model('Comment', Comment);